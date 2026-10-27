"""Resolve the project's pinned Node, independently of either assistant's PATH."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def resolve_node(root=ROOT):
    settings = json.loads((Path(root) / 'config/runtime.json').read_text(encoding='utf-8'))
    local = Path(root) / 'config/runtime.local.json'
    if local.exists():
        settings['node_executable'] = json.loads(local.read_text(encoding='utf-8-sig'))['node_executable']
    configured = os.environ.get('BATTLEBOOK_NODE') or settings.get('node_executable', 'node')
    executable = Path(shutil.which(configured) or configured)
    if not executable.is_absolute() or not executable.is_file():
        raise RuntimeError('pinned_node_missing:' + str(executable))
    version = subprocess.check_output([str(executable), '--version'], text=True).strip()
    if version != 'v' + settings['node_version']:
        raise RuntimeError('pinned_node_version_mismatch:' + version)
    return str(executable), version


def node_environment(executable):
    environment = dict(os.environ)
    environment['PATH'] = str(Path(executable).parent) + os.pathsep + environment.get('PATH', '')
    return environment


if __name__ == '__main__':
    executable, _version = resolve_node()
    raise SystemExit(subprocess.call([executable, *sys.argv[1:]], env=node_environment(executable)))
