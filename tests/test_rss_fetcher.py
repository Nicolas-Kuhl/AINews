"""Tests for concurrent feed fetching in fetch_all_feeds.

The per-feed fetch is monkeypatched so these run without network access.
"""

from __future__ import annotations

import time
import unittest

from ainews.fetchers import rss_fetcher
from ainews.models import RawNewsItem


def _raw(title: str) -> RawNewsItem:
    return RawNewsItem(title=title, url=f"https://x/{title}", source="s", fetched_via="rss")


class FetchAllFeedsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = rss_fetcher._fetch_one_feed

    def tearDown(self) -> None:
        rss_fetcher._fetch_one_feed = self._orig

    def test_aggregates_results_from_all_feeds(self) -> None:
        def fake(fc, timeout, max_items):
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": f"f{i}", "type": "rss"} for i in range(5)]
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5)
        self.assertEqual(sorted(i.title for i in items), ["f0", "f1", "f2", "f3", "f4"])

    def test_one_failing_feed_does_not_abort_batch(self) -> None:
        def fake(fc, timeout, max_items):
            if fc["name"] == "bad":
                raise RuntimeError("boom")
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": "ok1", "type": "rss"}, {"name": "bad", "type": "rss"},
                 {"name": "ok2", "type": "rss"}]
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5)
        self.assertEqual(sorted(i.title for i in items), ["ok1", "ok2"])

    def test_disabled_feeds_skipped(self) -> None:
        def fake(fc, timeout, max_items):
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": "on", "type": "rss"}, {"name": "off", "type": "rss", "enabled": False}]
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5)
        self.assertEqual([i.title for i in items], ["on"])

    def test_slow_feed_runs_concurrently_with_fast_ones(self) -> None:
        """Ten 0.2s feeds should finish in well under the 2s serial total."""
        def fake(fc, timeout, max_items):
            time.sleep(0.2)
            return [_raw(fc["name"])]

        rss_fetcher._fetch_one_feed = fake
        feeds = [{"name": f"f{i}", "type": "rss"} for i in range(10)]
        start = time.monotonic()
        items = rss_fetcher.fetch_all_feeds(feeds, timeout=5, max_workers=10)
        elapsed = time.monotonic() - start
        self.assertEqual(len(items), 10)
        self.assertLess(elapsed, 1.0)  # serial would be ~2.0s


if __name__ == "__main__":
    unittest.main()
