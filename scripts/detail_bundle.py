"""One-build private I/O bundle, checked against real public files by the JS gate."""
import json
from pathlib import Path


def load_bundle(path, build_id):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('build_id') != build_id or not isinstance(data.get('details'), dict):
        raise ValueError('stale_or_invalid_detail_bundle')
    for mid, detail in data['details'].items():
        if detail.get('id') != mid or len(detail.get('players', [])) != 10:
            raise ValueError('invalid_bundled_detail:' + mid)
    return data['details']
