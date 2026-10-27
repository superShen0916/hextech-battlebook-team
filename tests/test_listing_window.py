"""The listing window verdict must not be guessed from page lengths.

Regression for the 2026-10-23 finding: every friend's own match-ID listing looked
"complete" (last page shorter than requested) while the archive already held older
matches of the same player. The endpoint simply stops at a recent window.
"""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from listing import (classify_window, iso_to_ms, summarise,
                     STATUS_COMPLETE, STATUS_TRUNCATED, STATUS_SKIPPED, STATUS_UNKNOWN)


def window_of(listed, started, archived, listed_at_ms=None):
    return classify_window(listed, started, archived, listed_at_ms=listed_at_ms)


class ListingWindowTests(unittest.TestCase):
    def test_short_last_page_is_not_proof_of_complete_history(self):
        # 4 games listed, the newest 2 also held in the archive, 2 older ones only in
        # the archive -> the page walk ended at the endpoint's window, not at the start.
        started = {'M1': 1000, 'M2': 2000, 'M3': 500, 'M4': 100}
        result = window_of(['M1', 'M2'], started, ['M1', 'M2', 'M3', 'M4'])
        self.assertEqual(result['status'], STATUS_TRUNCATED)
        self.assertFalse(result['history_complete'])
        self.assertEqual(result['archived_beyond_window'], 2)
        self.assertEqual(result['oldest_listed_ms'], 1000)
        self.assertEqual(result['oldest_archived_ms'], 100)

    def test_listing_without_older_archive_games_is_complete(self):
        started = {'M1': 1000, 'M2': 2000, 'M3': 3000}
        result = window_of(['M1', 'M2', 'M3'], started, ['M2', 'M3'])
        self.assertEqual(result['status'], STATUS_COMPLETE)
        self.assertTrue(result['history_complete'])
        self.assertEqual(result['archived_beyond_window'], 0)

    def test_archived_match_inside_window_but_missing_is_a_real_bug(self):
        # M2 started after the oldest listed match yet never appeared in the listing:
        # a page was dropped, which is a collector defect rather than an upstream cap.
        started = {'M1': 1000, 'M3': 3000, 'M2': 2000}
        result = window_of(['M1', 'M3'], started, ['M1', 'M2', 'M3'], listed_at_ms=10_000)
        self.assertEqual(result['status'], STATUS_SKIPPED)
        self.assertEqual(result['archived_missing_inside_window'], 1)

    def test_matches_played_after_the_crawl_are_not_counted_as_skipped(self):
        started = {'M1': 1000, 'M2': 5000}
        result = window_of(['M1'], started, ['M1', 'M2'], listed_at_ms=2000)
        self.assertEqual(result['status'], STATUS_COMPLETE)
        self.assertEqual(result['archived_after_listing'], 1)
        self.assertEqual(result['archived_missing_inside_window'], 0)

    def test_record_window_flag_marks_the_1000_id_cap(self):
        started = {'M%d' % i: i for i in range(1000)}
        listed = ['M%d' % i for i in range(1000)]
        result = window_of(listed, started, listed)
        self.assertTrue(result['at_record_window'])
        self.assertEqual(result['listed'], 1000)
        self.assertEqual(result['status'], STATUS_COMPLETE)

    def test_empty_listing_is_unknown_not_complete(self):
        result = window_of([], {}, ['M1'])
        self.assertEqual(result['status'], STATUS_UNKNOWN)
        self.assertFalse(result['history_complete'])

    def test_iso_timestamps_parse_and_reject_junk(self):
        self.assertEqual(iso_to_ms('1970-01-01T00:00:01+00:00'), 1000)
        self.assertIsNone(iso_to_ms(''))
        self.assertIsNone(iso_to_ms('not-a-date'))

    def test_summarise_never_raises(self):
        self.assertIn('window=unknown', summarise(None))
        started = {'M1': 1000}
        self.assertIn('window=complete', summarise(window_of(['M1'], started, ['M1'])))


if __name__ == '__main__':
    unittest.main()
