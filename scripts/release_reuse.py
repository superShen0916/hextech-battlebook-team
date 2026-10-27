"""Candidate assembly and bounded slot rotation. Input/file APIs are re-exported for compatibility."""
import json
import os
import shutil
import uuid
from pathlib import Path
from release_files import file_hash, tree_hash
from release_inputs import (is_dataset, frontend_inputs, database_signature,
                            rating_week, data_inputs, data_outputs)


def read_state(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def can_reuse_frontend(receipt, inputs, dist):
    return (receipt.get('inputs') == inputs and Path(dist, 'index.html').is_file() and
            receipt.get('shell') == tree_hash(dist, lambda p: not is_dataset(p)))


def assemble_data_release(dist, public, target):
    """Refresh the fixed inactive slot without mutating the active release."""
    dist, public, target = map(Path, (dist, public, target))
    sources = {}
    for source in dist.rglob('*'):
        rel = source.relative_to(dist)
        if source.is_file() and not is_dataset(rel):
            sources[rel.as_posix()] = source
    for name in ('api', 'matches'):
        for source in (public / name).rglob('*'):
            if not source.is_file():
                continue
            rel = source.relative_to(public)
            sources[rel.as_posix()] = source
    return mirror_slot(target, sources)


def mirror_slot(target, sources, generated=()):
    """Atomic file replacements also detach legacy hard links safely.

    Only obsolete files in the inactive slot are removed. No whole directory
    is deleted per build, and a denied removal fails before active promotion.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or getattr(target, 'is_junction', lambda: False)():
        raise RuntimeError('unsafe_candidate_link')
    expected = set(sources) | set(generated)
    stats = {'reused_data_files': 0, 'copied_data_files': 0}
    for rel in expected:
        path = Path(rel)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise RuntimeError('unsafe_candidate_file:' + str(rel))
    for path in target.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise RuntimeError('unsafe_candidate_link:' + str(path))
    for rel, source in sources.items():
        source, dest = Path(source), target / rel
        if dest.is_file() and file_hash(source) == file_hash(dest):
            if is_dataset(Path(rel)):
                stats['reused_data_files'] += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_name('.' + dest.name + '.copy-' + uuid.uuid4().hex)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, dest)
            if is_dataset(Path(rel)):
                stats['copied_data_files'] += 1
        finally:
            temporary.unlink(missing_ok=True)
    for rel in generated:
        if not (target / rel).is_file():
            raise RuntimeError('missing_generated_shell:' + rel)
    for path in target.rglob('*'):
        if path.is_file() and path.relative_to(target).as_posix() not in expected:
            path.unlink()
    for path in sorted(target.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return stats


def assemble_frontend_release(public, target, generated):
    public = Path(public)
    sources = {p.relative_to(public).as_posix(): p for p in public.rglob('*') if p.is_file()}
    if set(sources) & set(generated):
        raise RuntimeError('public_file_shadows_generated_shell')
    mirror_slot(target, sources, generated)


def promote(candidate, dist, previous, build):
    candidate, dist, previous, build = map(Path, (candidate, dist, previous, build))
    if not previous.resolve().is_relative_to(build.resolve()) or previous.name != 'dist-previous':
        raise RuntimeError('unsafe_previous_path')
    rotation = build / 'rotation-previous'
    if rotation.exists():
        if candidate.exists():
            raise RuntimeError('unfinished_slot_rotation; inspect rotation-previous')
        os.replace(rotation, candidate)
    had_previous = previous.exists()
    if had_previous:
        os.replace(previous, rotation)
    try:
        if dist.exists():
            os.replace(dist, previous)
        os.replace(candidate, dist)
    except OSError:
        if previous.exists() and not dist.exists():
            os.replace(previous, dist)
        if rotation.exists() and not previous.exists():
            os.replace(rotation, previous)
        raise
    if rotation.exists():
        os.replace(rotation, candidate)
    return None
