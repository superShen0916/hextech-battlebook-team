"""Is a player's upstream match-ID listing really their whole history?

The SGP player listing (/match-history-query/v1/products/lol/player/{puuid}
?startIndex&count&tag) only serves a recent window:

* startIndex >= 1000 always returns an empty array (measured 2026-10-23);
* time-window parameters (startTime/endTime, beginTime, start/end, startDate)
  are ignored - the newest page comes back unchanged;
* the window ends by itself well before a heavy player's history does: for
  several friends the listing stops at 880-1000 IDs while the archive already
  holds older matches of the same player, recovered through other accounts.

So "the last page was shorter than requested" proves only that the crawl
reached the end of the *window*. It never proves the history starts there.
The archive is the only evidence that can tell the two apart:

* a match we hold that is OLDER than the oldest listed match  -> window truncated
* a match we hold that falls INSIDE the listed time range but is absent from the
  listing -> the enumerator itself dropped a page (a real collection bug)

This module is pure logic so both collectors and the reports share one verdict.
"""
from datetime import datetime

RECORD_WINDOW = 1000

STATUS_COMPLETE = 'complete'
STATUS_TRUNCATED = 'window_truncated'
STATUS_SKIPPED = 'skipped_pages'
STATUS_UNKNOWN = 'unknown'


def classify_window(listed_ids, started_ms, archived_ids=(), listed_at_ms=None):
    """Compare one player's listing against the matches we already hold.

    listed_ids: match IDs returned by the listing endpoint.
    started_ms: mapping match_key -> start timestamp in ms.
    archived_ids: match IDs the archive holds for the same player.
    listed_at_ms: when the listing was crawled; matches started after that moment
        cannot be in it, so they must not be counted as skipped pages.
    """
    listed = {mid for mid in listed_ids if isinstance(mid, str)}
    times = [started_ms[mid] for mid in listed if isinstance(started_ms.get(mid), (int, float))]
    oldest_listed = min(times) if times else None
    older, inside, newer = [], [], []
    for mid in set(archived_ids):
        if mid in listed:
            continue
        started = started_ms.get(mid)
        if oldest_listed is None or not isinstance(started, (int, float)):
            continue
        if started < oldest_listed:
            older.append(mid)
        elif isinstance(listed_at_ms, (int, float)) and started > listed_at_ms:
            newer.append(mid)
        else:
            inside.append(mid)
    if oldest_listed is None:
        status = STATUS_UNKNOWN
    elif inside:
        status = STATUS_SKIPPED
    elif older:
        status = STATUS_TRUNCATED
    else:
        status = STATUS_COMPLETE
    archived_times = [started_ms[m] for m in set(archived_ids) if isinstance(started_ms.get(m), (int, float))]
    return {'status': status,
            'history_complete': status == STATUS_COMPLETE,
            'listed': len(listed),
            'archived': len(set(archived_ids)),
            'archived_beyond_window': len(older),
            'archived_missing_inside_window': len(inside),
            'archived_after_listing': len(newer),
            'oldest_listed_ms': oldest_listed,
            'oldest_archived_ms': min(archived_times) if archived_times else None,
            'record_window': RECORD_WINDOW,
            'at_record_window': len(listed) >= RECORD_WINDOW,
            'older_archived_ids': sorted(older),
            'inside_window_missing_ids': sorted(inside)}


def archive_index(connection, puuid):
    """Return (match IDs, started_ms map) the archive holds for one player."""
    started = dict(connection.execute('SELECT match_key,started_ms FROM matches'))
    ids = [row[0] for row in connection.execute(
        'SELECT DISTINCT match_key FROM participants WHERE puuid=?', (puuid,))]
    return ids, started


def iso_to_ms(value):
    """Parse an ISO timestamp from a status/listing file into epoch milliseconds."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.timestamp() * 1000


def summarise(window):
    """One line for logs and status files; never raises on a partial dict."""
    if not isinstance(window, dict):
        return 'window=unknown'
    return 'window=%s listed=%s archived=%s older_archived=%s inside_missing=%s after_listing=%s oldest_listed=%s' % (
        window.get('status', 'unknown'), window.get('listed'), window.get('archived'),
        window.get('archived_beyond_window'), window.get('archived_missing_inside_window'),
        window.get('archived_after_listing'), window.get('oldest_listed_ms'))
