"""Explicit statistical exclusions; preserve original source responses for audit."""
import hashlib
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'data' / 'stat-exclusions.json'


def exclusions(path=CONFIG):
    if not Path(path).is_file():
        return {}
    rows = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return {row['public_match_id']: row['reason'] for row in rows}


def apply_policy(match, rules=None):
    rules = exclusions() if rules is None else rules
    public_id = 'm-' + hashlib.sha256(match['match_key'].encode()).hexdigest()[:20]
    if public_id in rules:
        match['stats_eligible'] = False
        match['exclusion_reason'] = rules[public_id]
    return match
