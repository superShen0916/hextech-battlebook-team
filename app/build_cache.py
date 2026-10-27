"""Optional local build cache. Public projections remain the source of truth.

Keys include complete semantic inputs and implementation files. Damaged or missing
entries are misses; cached data is never put directly on the publishing path.
"""
import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def implementation_key(directory):
    return digest([(p.name, hashlib.sha256(p.read_bytes()).hexdigest())
                   for p in sorted(Path(directory).glob('*.py'))])


class ProjectionCache:
    def __init__(self, directory, implementation):
        self.directory = Path(directory)
        self.implementation = implementation
        self.hits = self.misses = 0

    def get_or_compute(self, name, inputs, compute):
        key = digest([self.implementation, inputs])
        path = self.directory / (hashlib.sha256(name.encode()).hexdigest() + '.json')
        try:
            entry = json.loads(path.read_text(encoding='utf-8'))
            if entry['key'] == key and digest(entry['value']) == entry['sha256']:
                self.hits += 1
                return entry['value']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        value = compute()
        entry = {'key': key, 'sha256': digest(value), 'value': value}
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.directory, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(entry, stream, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.misses += 1
        return value
