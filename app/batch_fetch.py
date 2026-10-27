"""Cover a collector's fetch queue with paged SUMMARY requests instead of per-match ones.

SGP serves the same per-match payload two ways:

  /match-history-query/v3/product/lol/matchId/{id}/infoType/summary    one match
  /match-history-query/v1/products/lol/player/{puuid}/SUMMARY
        ?startIndex=N&count=M&tag=q_2400                              a page of matches

Both bodies carry the identical match object, so a collector may take the whole
queue from pages and keep the single-match route only as the fallback. Page order
is listing order (newest first) inside the same bounded window the listing
endpoint exposes (app/listing.py): a short or empty page marks the end of that
window, while a full page that misses an ID only means the ID sits further down,
so paging continues until the window ends or the page ceiling is reached.

Upstream refuses the paged route when the whole edge is saturated; collectors must
treat that as "retry later", not as "the route does not exist".

This module is pure bookkeeping so collectors and tests share the same rules;
the network call is passed in as `fetch_page(start, count)`.
"""

BATCH_PAGE = 50
MAX_PAGES = 20


def planned_pages(wanted, page_size=BATCH_PAGE, max_pages=MAX_PAGES):
    """How many pages are worth requesting for `wanted` queued matches.

    One page per `page_size` queued IDs, plus one page of slack for matches that
    are not queue 2400 or have fallen out of the window, never above the number
    of pages the window can hold.
    """
    if not isinstance(wanted, int) or wanted <= 0:
        return 0
    return min(max_pages, (wanted + page_size - 1) // page_size + 1)


def cover(wanted, fetch_page, page_size=BATCH_PAGE, max_pages=MAX_PAGES):
    """Fetch pages until every wanted ID is matched or the window runs out.

    wanted: iterable of match IDs the collector still has to store.
    fetch_page(start, count): returns [(match_id, raw_payload), ...] for one page.

    Returns {'matched': {match_id: raw}, 'pages': n, 'stop': reason,
             'missing': [ids not seen in the pages]}. `stop` is one of
    'covered' (nothing left), 'empty_page', 'window_end' (short page: the
    listing window ended) or 'page_ceiling'. `missing` IDs must fall back to
    per-match fetches: they are outside the window, so paging further is waste.
    """
    remaining = {mid for mid in wanted if isinstance(mid, str) and mid}
    matched = {}
    pages = 0
    stop = 'page_ceiling'
    for index in range(planned_pages(len(remaining), page_size, max_pages)):
        if not remaining:
            stop = 'covered'
            break
        page = fetch_page(index * page_size, page_size) or []
        pages += 1
        if not page:
            stop = 'empty_page'
            break
        for mid, raw in page:
            if mid in remaining:
                matched[mid] = raw
                remaining.discard(mid)
        if len(page) < page_size:
            stop = 'window_end'
            break
    return {'matched': matched, 'pages': pages, 'stop': stop, 'missing': sorted(remaining)}
