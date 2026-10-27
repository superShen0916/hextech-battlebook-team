"""无人值守的每日更新：客户端在线才采集，然后构建并同步发布目录。

托管发布不在这里做——那需要 WorkBuddy 的发布能力，由调用方（skill / agent）完成。
本脚本只保证三件事：

1. 客户端不在时不硬拉、不报错，明确记为 skipped，不假装采集过；
2. 采集失败不进入构建，不把部分完成当成成功；
3. 构建成功后给出 publish_needed，交给调用方决定是否上线。

用法：
  python scripts/nightly.py                 # 预检 → 采集(条件) → 构建 → 报告
  python scripts/nightly.py --skip-collect  # 只构建，不碰客户端
  python scripts/nightly.py --build-anyway  # 采集非零仍构建（显式覆盖，默认不）
  python scripts/nightly.py --mark-published  # 发布成功后回写，避免重复发布

退出码：0 完成（含客户端不在的降级）/ 1 失败。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'scripts'))

from project_paths import DATABASE, RELEASE  # noqa: E402
from workflow_guard import check_database_routes  # noqa: E402
from snapshot_io import write_json  # noqa: E402 - shared atomic writer
from sync_release import check_release  # noqa: E402
from public_site import _exclusive_lock  # noqa: E402

BEIJING = timezone(timedelta(hours=8))
COLLECT = ROOT / 'work/gopher-pilot-20261021/scripts/sync_new_matches.py'
BUILD_ENTRY = ROOT / 'scripts/build_release.py'
RESULT = ROOT / 'work/build/release-result.json'
STATE = ROOT / 'work/build/nightly-state.json'
REPORTS = ROOT / 'outputs/nightly'
COLLECT_TIMEOUT = 3600
BUILD_TIMEOUT = 2400
KEEP_REPORTS = 90


def now():
    return datetime.now(BEIJING)


def stamp():
    return now().strftime('%Y-%m-%dT%H%M')


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def client_status():
    """只读探测；凭据留在内存，不落盘不打印。"""
    try:
        from lcu_probe import processes, discover, ProbeError
    except ImportError as error:  # pragma: no cover
        return {'online': False, 'reason': 'lcu_probe_import_failed:' + str(error)}
    try:
        rows = processes()
    except ProbeError as error:
        return {'online': False, 'reason': str(error)}
    try:
        _port, _token, method = discover(rows)
    except ProbeError as error:
        return {'online': False, 'reason': str(error)}
    return {'online': True, 'reason': 'lcu_reachable', 'discovery': method}


def run(script, extra, timeout):
    started = time.perf_counter()
    try:
        result = subprocess.run([sys.executable, str(script), *extra], cwd=str(ROOT),
                                capture_output=True, text=True, timeout=timeout,
                                encoding='utf-8', errors='replace')
        code, out, err = result.returncode, result.stdout or '', result.stderr or ''
    except subprocess.TimeoutExpired:
        code, out, err = 124, '', 'timeout_after_%ds' % timeout
    except OSError as error:
        code, out, err = 127, '', str(error)
    release = None
    if code == 0:
        for line in out.splitlines():
            if line.startswith('RELEASE_READY '):
                try:
                    value = json.loads(line[len('RELEASE_READY '):])
                    if isinstance(value, dict):
                        release = value
                except ValueError:
                    pass
    return {'exit': code, 'seconds': round(time.perf_counter() - started, 1),
            'release_result': release,
            'tail': [line for line in out.strip().splitlines() if line.strip()][-8:],
            'stderr': err.strip()[-800:]}


def prune_reports():
    try:
        files = sorted(REPORTS.glob('*.json'))
        for path in files[:-KEEP_REPORTS]:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def retired_builds():
    """Only legacy retired directories; new builds reuse bounded fixed slots."""
    count = total = 0
    for path in (ROOT / 'work/build').glob('dist-retired-*'):
        if not path.is_dir():
            continue
        count += 1
        for item in path.rglob('*'):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                pass
    return {'count': count, 'mb': round(total / 1048576, 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-collect', action='store_true', help='不探测客户端、不采集，只构建')
    parser.add_argument('--build-anyway', action='store_true', help='采集非零退出仍继续构建')
    parser.add_argument('--mark-published', action='store_true', help='把当前 build_id 记为已发布')
    parser.add_argument('--probe-only', action='store_true', help='只探测客户端是否登录在线；不采集、不构建、不写状态。退出码 0=在线，2=未登录')
    args = parser.parse_args()

    state = read_json(STATE, {}) or {}
    current_build = read_json(RESULT, {}) or {}

    if args.mark_published:
        try:
            with _exclusive_lock(ROOT / 'work/build/release.lock') as acquired:
                if not acquired:
                    raise RuntimeError('release_already_running')
                current_build = read_json(RESULT, {}) or {}
                verified = check_release()
                if (current_build.get('release_directory_synced') is not True or
                        verified['build_id'] != current_build.get('build_id') or
                        current_build.get('artifact_sha256', verified['artifact_sha256']) != verified['artifact_sha256']):
                    raise RuntimeError('unverified_build_result_to_mark')
                state = read_json(STATE, {}) or {}
                state['last_published_build_id'] = verified['build_id']
                state['last_published_artifact_sha256'] = verified['artifact_sha256']
                state['last_published_at'] = now().isoformat(timespec='seconds')
                write_json(STATE, state)
            print(json.dumps({'ok': True, 'marked_published': verified['build_id'],
                              'artifact_sha256': verified['artifact_sha256']}, ensure_ascii=False))
            return 0
        except (OSError, ValueError, RuntimeError) as error:
            print(json.dumps({'ok': False, 'reason': str(error)}, ensure_ascii=False))
            return 1

    if args.probe_only:
        # 定时任务第 1 步：客户端没登录就拉不了战绩，整个流程直接退。
        client = client_status()
        print(json.dumps({'client': client}, ensure_ascii=False))
        return 0 if client.get('online') else 2

    report = {'run_id': stamp(), 'started_at': now().isoformat(timespec='seconds'),
              'reasons': [], 'ok': False}
    try:
        # 1. 唯一库与身份。失败直接停，不进任何写库步骤。
        try:
            report['database'] = check_database_routes(ROOT)
        except Exception as error:
            report['reasons'].append('database_routes_failed:' + str(error))
            raise

        # 2. 客户端探测
        if args.skip_collect:
            report['client'] = {'online': None, 'reason': 'skipped_by_flag'}
        else:
            report['client'] = client_status()

        # 3. 采集（仅在客户端在线时）
        collect = {'attempted': False}
        if args.skip_collect:
            collect['reason'] = 'skipped_by_flag'
        elif not report['client'].get('online'):
            collect['reason'] = 'client_not_running'
        else:
            collect['attempted'] = True
            collect.update(run(COLLECT, ['--yes'], COLLECT_TIMEOUT))
            collect['ok'] = collect['exit'] == 0
            if not collect['ok']:
                report['reasons'].append('collect_exit_%d' % collect['exit'])
        report['collect'] = collect

        # 4. 构建。采集失败默认不进构建，避免把不完整的采集当成功发布。
        blocked = collect.get('attempted') and not collect.get('ok') and not args.build_anyway
        if not args.skip_collect and not report['client'].get('online'):
            report['build'] = {'attempted': False, 'reason': 'client_not_running'}
            report['reasons'].append('client_not_logged_in')
        elif blocked:
            report['build'] = {'attempted': False, 'reason': 'collect_failed'}
            report['reasons'].append('build_skipped_after_collect_failure')
        else:
            build = {'attempted': True}
            build.update(run(BUILD_ENTRY, ['--data-only', '--sync'], BUILD_TIMEOUT))
            build['ok'] = build['exit'] == 0
            if not build['ok']:
                report['reasons'].append('build_exit_%d' % build['exit'])
            else:
                # Require this process's success receipt as well as the on-disk
                # result. A previous successful build is never this run's output.
                fresh = build.pop('release_result', None)
                result = read_json(RESULT, {}) or {}
                manifest = read_json(RELEASE / 'api/manifest.json', {}) or {}
                if (not isinstance(fresh, dict) or not fresh.get('build_id')
                        or fresh != result or fresh.get('release_directory_synced') is not True
                        or manifest.get('build_id') != fresh['build_id']
                        or not re.fullmatch(r'[a-f0-9]{64}', str(fresh.get('artifact_sha256', '')))):
                    build['ok'] = False
                    report['reasons'].append('build_result_unverified')
                else:
                    for key in ('build_id', 'artifact_sha256', 'data_unchanged', 'frontend_reused', 'release_directory_synced'):
                        build[key] = fresh.get(key)
            build.pop('release_result', None)
            report['build'] = build

        # Data IDs can stay the same after a CSS/JS-only rebuild. Publication is
        # about the complete artifact, shared with manual workflow receipts.
        built = report.get('build') or {}
        built_id = built.get('build_id') if built.get('ok') else None
        last_id = state.get('last_published_build_id')
        artifact = built.get('artifact_sha256') if built.get('ok') else None
        last_artifact = state.get('last_published_artifact_sha256')
        report['publish'] = {'needed': bool(artifact and artifact != last_artifact),
                             'current_build_id': built_id,
                             'last_published_build_id': last_id,
                             'current_artifact_sha256': artifact,
                             'last_published_artifact_sha256': last_artifact,
                             'release_directory': str(RELEASE)}
        if report['publish']['needed']:
            report['reasons'].append('build_not_yet_published')

        # Team data distribution is opt-in on the publisher only. It is not hosting.
        config = read_json(ROOT / 'config/team.local.json', {}) or {}
        if config.get('upload_after_nightly') and built.get('ok'):
            previous_upload = read_json(ROOT / 'work/build/team-upload.json', {}) or {}
            if (previous_upload.get('build_id') == built_id and
                    previous_upload.get('artifact_sha256') == artifact):
                report['team_data'] = {'ok': True, 'skipped': 'already_uploaded'}
            else:
                try:
                    from team_data import publish
                    uploaded = publish(ROOT, config['repository'])
                    uploaded['artifact_sha256'] = artifact
                    write_json(ROOT / 'work/build/team-upload.json', uploaded)
                    report['team_data'] = uploaded
                except Exception as error:
                    report['team_data'] = {'ok': False, 'error': str(error)}
                    report['reasons'].append('team_data_upload_failed')

        report['retired_builds'] = retired_builds()
        if report['retired_builds']['mb'] > 1024:
            report['reasons'].append('retired_builds_piling_up')

        report['ok'] = not any(r.startswith(('database_routes_failed', 'collect_exit', 'build_exit', 'build_result_'))
                               for r in report['reasons'])
    except Exception as error:  # noqa: BLE001 - 无人值守入口必须留下失败原因
        report['reasons'].append('fatal:' + type(error).__name__ + ':' + str(error)[:200])

    report['finished_at'] = now().isoformat(timespec='seconds')
    write_json(REPORTS / (report['run_id'] + '.json'), report)
    write_json(REPORTS / 'latest.json', report)
    state['last_run'] = {k: report.get(k) for k in ('run_id', 'ok', 'client', 'reasons')}
    write_json(STATE, state)
    prune_reports()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
