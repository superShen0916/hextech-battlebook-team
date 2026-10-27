"""Content inventories for one locked release operation; no persistent hash cache.

An inventory is a snapshot of file bytes, not a promise based on size or mtime.
Callers hold release.lock while reusing it. A later command always reads afresh.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import shutil
from types import MappingProxyType
import uuid


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


@dataclass(frozen=True)
class FileTree:
    root: Path
    files: Mapping[str, str]

    def __post_init__(self):
        for name in self.files:
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.as_posix() != name:
                raise ValueError('unsafe_release_file:' + name)
        object.__setattr__(self, 'root', Path(self.root).resolve())
        object.__setattr__(self, 'files', MappingProxyType(dict(self.files)))

    def digest_for(self, select=lambda p: True):
        digest = hashlib.sha256()
        for name in sorted(self.files):
            if select(Path(name)):
                digest.update(name.encode() + b'\0')
                digest.update(bytes.fromhex(self.files[name]))
        return digest.hexdigest()

    @property
    def digest(self):
        return self.digest_for()


def inspect_tree(directory, select=lambda p: True, *, missing_ok=False):
    base = Path(directory)
    if _linked(base):
        raise RuntimeError('release_tree_is_link:' + str(base))
    if not base.is_dir() and not missing_ok:
        raise RuntimeError('release_tree_missing:' + str(base))
    files = {}
    for path in sorted(base.rglob('*')):
        relative = path.relative_to(base)
        if _linked(path):
            raise RuntimeError('release_file_is_link:' + str(path))
        if path.is_file() and select(relative):
            files[relative.as_posix()] = file_hash(path)
    return FileTree(base.resolve(), files)


def tree_hash(directory, select=lambda p: True):
    """Compatibility API for optional input directories as well as release trees."""
    return inspect_tree(directory, select, missing_ok=True).digest


def sync_tree(source, target):
    """Mirror one verified inventory, then verify the complete destination.

    The source inventory was read by the caller under the same lock. Unchanged
    destination bytes are hashed, never accepted on timestamps. Changed files
    use atomic replacement. A copy/delete/verification failure never returns a
    successful receipt; callers must not publish a partially synchronized tree.
    """
    target = Path(target)
    source_root = source.root.resolve()
    target_root = target.resolve()
    if (source_root == target_root or source_root in target_root.parents or
            target_root in source_root.parents):
        raise RuntimeError('overlapping_release_trees')
    current = inspect_tree(target, missing_ok=True)
    changed = sorted(name for name, digest in source.files.items()
                     if current.files.get(name) != digest)
    obsolete = sorted(set(current.files) - set(source.files))
    for name in changed:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('unsafe_release_file:' + name)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name('.' + destination.name + '.copy-' + uuid.uuid4().hex)
        try:
            shutil.copy2(source.root / relative, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    for name in obsolete:
        (target / name).unlink()
    # If nothing was changed, current already is the complete fresh check.
    verified = inspect_tree(target) if changed or obsolete else current
    if verified.files != source.files:
        raise RuntimeError('synced_content_mismatch; do not publish; rerun preparation')
    return {'files': len(verified.files), 'copied': len(changed), 'removed': len(obsolete),
            'artifact_sha256': verified.digest}
