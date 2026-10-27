"""Validate the public Git checkout without downloading battle data or dependencies."""
from pathlib import Path
import argparse
import json
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_PATTERNS = (
    re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'AKID[A-Za-z0-9]{28,}'),
)
FORBIDDEN_PARTS = {'.git', 'node_modules', '__pycache__', 'backups', 'outputs', '_archive'}


def inspect(root, names):
    root = Path(root).resolve()
    names = set(names)
    errors = []
    for name in ('README.md', 'AGENTS.md', 'LICENSE'):
        if name not in names or not (root/name).is_file():
            errors.append('missing required file: '+name)
    for name in sorted(names):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            errors.append('unsafe tracked path: '+name)
            continue
        path = root/relative
        if path.is_symlink() or root not in path.resolve().parents:
            errors.append('tracked file leaves repository or uses a symlink: '+name)
            continue
        if not path.is_file():
            errors.append('missing tracked file: '+name)
            continue
        if (FORBIDDEN_PARTS.intersection(relative.parts) or relative.parts[0] == 'data' or
                relative.suffix in ('.sqlite', '.db', '.log', '.pyc') or
                (relative.name.startswith('.env') and relative.name != '.env.example') or
                name in ('STATUS.md', 'WORKBUDDY-HANDOFF.txt') or
                name.startswith('docs/history/')):
            errors.append('local data or operations file tracked: '+name)
            continue
        raw = path.read_bytes()
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(raw):
                # Diagnostics identify only the file, never a matched value.
                errors.append('credential marker found: '+name)
                break
        if relative.suffix == '.json':
            try:
                json.loads(raw.decode('utf-8-sig'))
            except (ValueError, UnicodeError):
                errors.append('invalid JSON: '+name)
        if relative.suffix == '.md':
            text = raw.decode('utf-8-sig')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.strip().strip('<>').split('#', 1)[0]
                if not target or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target):
                    continue
                destination = (path.parent/target).resolve()
                if root not in destination.parents and destination != root:
                    errors.append('documentation link leaves repository: '+name)
                elif not destination.exists():
                    errors.append('broken documentation link: '+name+' -> '+target)
        if name.startswith('.github/workflows/') and relative.suffix in ('.yml', '.yaml'):
            text = raw.decode('utf-8')
            for action in re.findall(r'(?m)^\s*-?\s*uses:\s*([^\s#]+)', text):
                if action.startswith('./'):
                    continue
                if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}', action):
                    errors.append('action must use an immutable commit SHA: '+name)
            if re.search(r'(?m)^[^#\n]*\bpull_request_target\b', text):
                errors.append('privileged PR execution requires explicit security review: '+name)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    raw = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root)
    names = [name for name in raw.decode('utf-8').split('\0') if name]
    errors = inspect(root, names)
    print(json.dumps({'ok': not errors, 'tracked_files': len(names), 'errors': errors}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
