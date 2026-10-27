import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from batch_fetch import cover, planned_pages, BATCH_PAGE, MAX_PAGES  # noqa: E402
from core import (SourceError, TencentSource, parse_summary_page,  # noqa: E402
                  summary_page_path, normalize)


def summary(gid, queue=2400, mode='KIWI'):
    members = []
    for pid in range(1, 11):
        members.append({'participantId': pid, 'puuid': 'P-%d' % pid,
                        'teamId': 100 if pid <= 5 else 200, 'championId': pid,
                        'win': pid <= 5, 'kills': 1, 'deaths': 1, 'assists': 1})
    return {'platformId': 'HN1', 'gameId': gid, 'queueId': queue, 'gameMode': mode,
            'gameVersion': '16.20.1', 'gameCreation': 1792500000000, 'gameDuration': 600,
            'endOfGameResult': 'GameComplete', 'participants': members}


def page_of(ids, start, count):
    return [('HN1_%d' % mid, summary(mid)) for mid in ids[start:start + count]]


class PlannedPagesTest(unittest.TestCase):
    def test_empty_queue_requests_nothing(self):
        self.assertEqual(planned_pages(0), 0)
        self.assertEqual(planned_pages(-3), 0)

    def test_one_slack_page_for_small_queue(self):
        self.assertEqual(planned_pages(1), 2)
        self.assertEqual(planned_pages(BATCH_PAGE), 2)

    def test_grows_with_the_queue_but_stops_at_the_window(self):
        self.assertEqual(planned_pages(BATCH_PAGE + 1), 3)
        self.assertEqual(planned_pages(10 ** 6), MAX_PAGES)


class CoverTest(unittest.TestCase):
    def test_single_page_covers_a_small_tail(self):
        listing = [101, 102, 103, 104]
        wanted = ['HN1_101', 'HN1_102', 'HN1_103']
        result = cover(wanted, lambda s, c: page_of(listing, s, c))
        self.assertEqual(sorted(result['matched']), wanted)
        self.assertEqual(result['pages'], 1)
        self.assertEqual(result['stop'], 'window_end')  # short page ends the window
        self.assertEqual(result['missing'], [])

    def test_queue_beyond_first_page_keeps_paging(self):
        listing = list(range(1000, 900, -1))  # 100 newest IDs
        wanted = ['HN1_%d' % mid for mid in listing]
        result = cover(wanted, lambda s, c: page_of(listing, s, c))
        self.assertEqual(len(result['matched']), 100)
        self.assertEqual(result['stop'], 'covered')
        self.assertEqual(result['pages'], 2)  # 100/50; the slack page is never spent

    def test_ids_outside_the_window_are_reported_missing(self):
        listing = [201, 202]
        result = cover(['HN1_201', 'HN1_999'], lambda s, c: page_of(listing, s, c))
        self.assertEqual(sorted(result['matched']), ['HN1_201'])
        self.assertEqual(result['missing'], ['HN1_999'])

    def test_empty_page_stops_the_sweep(self):
        result = cover(['HN1_1'], lambda s, c: [])
        self.assertEqual(result['pages'], 1)
        self.assertEqual(result['stop'], 'empty_page')
        self.assertEqual(result['missing'], ['HN1_1'])

    def test_page_ceiling_is_respected(self):
        listing = list(range(5000, 0, -1))
        calls = []

        def fetch(start, count):
            calls.append(start)
            return page_of(listing, start, count)

        result = cover(['HN1_1'], fetch, page_size=10, max_pages=3)
        self.assertEqual(len(calls), 2)  # one page + one slack page, capped at 3
        self.assertEqual(result['stop'], 'page_ceiling')
        self.assertEqual(result['missing'], ['HN1_1'])

    def test_none_page_is_treated_as_empty(self):
        result = cover(['HN1_1'], lambda s, c: None)
        self.assertEqual(result['stop'], 'empty_page')


class SummaryPagePathTest(unittest.TestCase):
    def test_builds_the_documented_route(self):
        path = summary_page_path('0b282444-ef49-5c5e-8f20-ba5cf2705c83', 0, 50)
        self.assertEqual(path, '/match-history-query/v1/products/lol/player/'
                               '0b282444-ef49-5c5e-8f20-ba5cf2705c83/SUMMARY'
                               '?startIndex=0&count=50&tag=q_2400')

    def test_queue_tag_can_be_swapped(self):
        self.assertIn('tag=q_450', summary_page_path('PUUID', 0, 5, tag='q_450'))

    def test_rejects_path_injection_and_bad_windows(self):
        for args in (('PUUID/../x', 0, 10), ('', 0, 10), ('PUUID', -1, 10),
                     ('PUUID', 0, 0), ('PUUID', 0, 101), ('PUUID', 0, True)):
            with self.assertRaises(SourceError):
                summary_page_path(*args)
        with self.assertRaises(SourceError):
            summary_page_path('PUUID', 0, 10, tag='q_2400&x=1')


class ParseSummaryPageTest(unittest.TestCase):
    def test_unwraps_json_and_derives_match_id(self):
        result = {'games': [{'metadata': {'x': 1}, 'json': summary(77)}]}
        page = parse_summary_page(result)
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0][0], 'HN1_77')
        self.assertEqual(page[0][1]['gameId'], 77)

    def test_inner_payload_satisfies_the_shared_validator(self):
        raw = parse_summary_page({'games': [{'json': summary(78)}]})[0][1]
        match = normalize(raw, 'P-1', expected_id='HN1_78')
        self.assertEqual(match['match_key'], 'HN1_78')
        self.assertEqual(len(match['participants']), 10)

    def test_rejects_shapes_that_are_not_a_page(self):
        for payload in ({}, {'games': {}}, {'games': ['x']}, {'games': [{'json': {}}]},
                        {'games': [{'json': dict(summary(1), gameId='abc')}]}):
            with self.assertRaises(SourceError):
                parse_summary_page(payload)


class SourceMethodTest(unittest.TestCase):
    def test_summary_page_uses_the_paged_route(self):
        source = object.__new__(TencentSource)
        seen = {}

        def fake_get(path, retries=1, diagnostic=None, timeout=15):
            seen['path'], seen['timeout'] = path, timeout
            return {'games': [{'json': summary(55)}]}

        source.get = fake_get
        page = source.summary_page('PUUID', 0, 50)
        self.assertEqual(page[0][0], 'HN1_55')
        self.assertIn('/SUMMARY?startIndex=0&count=50', seen['path'])
        self.assertGreaterEqual(seen['timeout'], 30)


if __name__ == '__main__':
    unittest.main()
