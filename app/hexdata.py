"""Locally imported Hexdata estimates; this module never calls Hexdata."""
from datetime import datetime
import json
import math
from pathlib import Path

SOURCE_URL = 'https://hexdata.com.cn/matchmaking-position'


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return value if parsed.tzinfo is not None else None
    except ValueError:
        return None


def public_rating(value=None):
    """Whitelist the estimate; never project lookup identities or extra fields."""
    value = value if isinstance(value, dict) else {}
    status = value.get('status', 'not_queried')
    if status not in ('estimated', 'pending', 'not_queried', 'unavailable'):
        status = 'unavailable'
    score, top = value.get('score'), value.get('top_percent')
    queried = _time(value.get('queried_at'))
    valid = (type(score) is int and score >= 0 and type(top) in (int, float)
             and math.isfinite(top) and 0 <= top <= 100 and queried is not None)
    if status == 'estimated' and not valid:
        status = 'unavailable'
    return {'status': status, 'score': score if status == 'estimated' else None,
            'top_percent': top if status == 'estimated' else None,
            'queried_at': queried if status == 'estimated' else None,
            'matches_through': _time(value.get('matches_through')) if status == 'estimated' else None,
            'source': 'Hexdata', 'source_url': SOURCE_URL}


def load_ratings(directory):
    path = Path(directory) / 'hexdata-ratings.json'
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version') != 1 or not isinstance(data.get('ratings'), dict):
            raise ValueError('invalid_rating_file')
        return {key: public_rating(row) for key, row in data['ratings'].items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'_unavailable': True}


def rating_for(player, ratings=None):
    ratings = ratings or {}
    row = ratings.get((player or {}).get('puuid'))
    return public_rating(row or {'status': 'unavailable' if ratings.get('_unavailable') else 'not_queried'})
