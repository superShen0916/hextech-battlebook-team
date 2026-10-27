"""Collector scope: accounts whose match history we stop pulling but keep in the archive.

Three lists decide three different things, and they are deliberately separate:

  data/public-profiles.json      -> who appears on the site (37 players)
  data/stat-exclusions.json      -> which matches are left out of the statistics
  data/collection-exclusions.json -> whose listings and detail tails we stop fetching

Excluding an account here changes nothing about what is already stored: its
archived matches, account_matches links and discovered rows stay as they are, and
a new match it plays in still reaches the archive through the other players'
listings plus attribution. Move the entry out of the JSON to resume collecting.
"""
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / 'data' / 'collection-exclusions.json'


def excluded_puuids(path=CONFIG):
    """PUUIDs the collectors must skip. Missing or unreadable config means nothing excluded."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    entries = data.get('excluded') or []
    return {str(item['puuid']) for item in entries if isinstance(item, dict) and item.get('puuid')}
