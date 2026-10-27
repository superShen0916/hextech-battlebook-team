"""Shared build paths and atomic JSON writes; never treat summaries as archives."""
import errno
import json
import os
import tempfile
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from project_paths import BUILD, FRONTEND
FULL = BUILD / 'snapshot.full.json'
API = FRONTEND / 'public/api'


def load_full(path=FULL):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('snapshot_kind') != 'full' or data.get('profiles_index'):
        raise ValueError('Requires full snapshot. Run export_public_snapshot.py; summary input is refused.')
    players = data.get('players') or []
    if not players:
        raise ValueError('empty_players')
    for row in players:
        if row.get('has_detail') or len(row.get('recent', [])) != row.get('coverage', {}).get('saved'):
            raise ValueError('truncated_profile_input: ' + row.get('id', '?'))
        if 'by_champion' not in row or 'reports' not in row:
            raise ValueError('missing_profile_sections: ' + row.get('id', '?'))
    return data


def _replace_atomic(temporary, path, attempts=8, delay=0.06):
    """os.replace 的退避重试。

    Windows 上目标文件被实时扫描、索引或预览服务短暂打开时，替换会抛 WinError 5/32
    （Python 归一为 EACCES/EPERM）。这类占用是瞬态的，退避重试即可，不改变"先写临时文件
    再原子替换"的语义，也不会产生半截 JSON。
    """
    for attempt in range(attempts):
        try:
            os.replace(temporary, path)
            return
        except OSError as error:
            transient = error.errno in (errno.EACCES, errno.EPERM, errno.EBUSY)
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        _replace_atomic(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
